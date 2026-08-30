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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-102: pet creation applies the constraints its request body
 * declares.
 *
 * Passability: Apply the constraints already declared on the request record by
 * annotating the create parameter for validation. The fixture posts an empty name,
 * which the record's own size constraint rejects once it is applied.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
@WebMvcTest(PetResource.class)
@ActiveProfiles("test")
class PetCreationValidationAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    PetRepository petRepository;

    @MockitoBean
    OwnerRepository ownerRepository;

    private Owner anOwner() {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName("Franklin");
        return owner;
    }

    @Test
    void shouldRejectAnEmptyName() throws Exception {
        given(ownerRepository.findById(1)).willReturn(Optional.of(anOwner()));

        mvc.perform(post("/owners/1/pets")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"id\":0,\"name\":\"\",\"birthDate\":\"2020-01-01\",\"typeId\":6}"))
            .andExpect(status().isBadRequest());

        verify(petRepository, never()).save(any(Pet.class));
    }

    @Test
    void shouldStillCreateAPetFromAValidBody() throws Exception {
        Owner owner = anOwner();
        PetType type = new PetType();
        type.setId(6);
        Pet saved = new Pet();
        saved.setId(4);
        saved.setName("Basil");
        saved.setType(type);

        given(ownerRepository.findById(1)).willReturn(Optional.of(owner));
        given(petRepository.findPetTypeById(6)).willReturn(Optional.of(type));
        given(petRepository.save(any(Pet.class))).willReturn(saved);

        mvc.perform(post("/owners/1/pets")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"id\":0,\"name\":\"Basil\",\"birthDate\":\"2020-01-01\",\"typeId\":6}"))
            .andExpect(status().isCreated());

        verify(petRepository).save(any(Pet.class));
    }
}
