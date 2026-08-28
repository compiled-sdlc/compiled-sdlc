package org.springframework.samples.petclinic.customers.web;

import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.customers.model.Owner;
import org.springframework.samples.petclinic.customers.model.OwnerRepository;
import org.springframework.samples.petclinic.customers.model.Pet;
import org.springframework.samples.petclinic.customers.model.PetRepository;
import org.springframework.samples.petclinic.customers.model.PetType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-111: neither writing path saves a pet whose type does not
 * exist, and both answer a bad request rather than a missing resource.
 */
@WebMvcTest(PetResource.class)
@ActiveProfiles("test")
class PetTypeRefusedAcceptanceTest {

    private static final int KNOWN_TYPE = 6;

    private static final int UNKNOWN_TYPE = 999;

    @Autowired
    MockMvc mvc;

    @MockitoBean
    PetRepository petRepository;

    @MockitoBean
    OwnerRepository ownerRepository;

    private String body(int id, int typeId) {
        return "{\"id\":" + id + ",\"name\":\"Basil\",\"birthDate\":\"2020-01-01\",\"typeId\":" + typeId + "}";
    }

    private void givenTheTypesThatExist() {
        PetType known = new PetType();
        known.setId(KNOWN_TYPE);
        known.setName("hamster");
        given(petRepository.findPetTypeById(KNOWN_TYPE)).willReturn(Optional.of(known));
        given(petRepository.findPetTypeById(UNKNOWN_TYPE)).willReturn(Optional.empty());
    }

    private void givenAnOwnerAndAPet() {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName("Franklin");
        given(ownerRepository.findById(1)).willReturn(Optional.of(owner));

        Pet pet = new Pet();
        pet.setId(2);
        pet.setName("Basil");
        given(petRepository.findById(2)).willReturn(Optional.of(pet));
        given(petRepository.save(any(Pet.class))).willAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void shouldRefuseCreatingAPetWithATypeThatDoesNotExist() throws Exception {
        givenTheTypesThatExist();
        givenAnOwnerAndAPet();

        mvc.perform(post("/owners/1/pets")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(0, UNKNOWN_TYPE)))
            .andExpect(status().isBadRequest());

        verify(petRepository, never()).save(any(Pet.class));
    }

    @Test
    void shouldRefuseUpdatingAPetWithATypeThatDoesNotExist() throws Exception {
        givenTheTypesThatExist();
        givenAnOwnerAndAPet();

        mvc.perform(put("/owners/1/pets/2")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(2, UNKNOWN_TYPE)))
            .andExpect(status().isBadRequest());

        verify(petRepository, never()).save(any(Pet.class));
    }

    @Test
    void shouldStillCreateAPetWhoseTypeExists() throws Exception {
        givenTheTypesThatExist();
        givenAnOwnerAndAPet();

        mvc.perform(post("/owners/1/pets")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(0, KNOWN_TYPE)))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.name").value("Basil"))
            .andExpect(jsonPath("$.type.id").value(KNOWN_TYPE));
    }

    @Test
    void shouldStillUpdateAPetWhoseTypeExists() throws Exception {
        givenTheTypesThatExist();
        givenAnOwnerAndAPet();

        mvc.perform(put("/owners/1/pets/2")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(2, KNOWN_TYPE)))
            .andExpect(status().isNoContent());

        verify(petRepository).save(any(Pet.class));
    }
}
