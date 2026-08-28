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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-101: the pet named in the request path is the pet updated.
 */
@WebMvcTest(PetResource.class)
@ActiveProfiles("test")
class PetUpdatePathAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    PetRepository petRepository;

    @MockitoBean
    OwnerRepository ownerRepository;

    private static final String BODY_FOR_PET_2 =
        "{\"id\":2,\"name\":\"Basil\",\"birthDate\":\"2020-01-01\",\"typeId\":6}";

    private static final String BODY_FOR_PET_3 =
        "{\"id\":3,\"name\":\"Basil\",\"birthDate\":\"2020-01-01\",\"typeId\":6}";

    private Pet aPet(int id) {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName("Franklin");
        Pet pet = new Pet();
        pet.setId(id);
        pet.setName("Leo");
        PetType type = new PetType();
        type.setId(6);
        pet.setType(type);
        owner.addPet(pet);
        return pet;
    }

    @Test
    void shouldUpdateThePetNamedInThePath() throws Exception {
        Pet pet = aPet(2);
        given(petRepository.findById(2)).willReturn(Optional.of(pet));
        given(petRepository.findPetTypeById(6)).willReturn(Optional.of(pet.getType()));
        given(petRepository.save(any(Pet.class))).willReturn(pet);

        mvc.perform(put("/owners/1/pets/2")
                .contentType(MediaType.APPLICATION_JSON)
                .content(BODY_FOR_PET_2))
            .andExpect(status().isNoContent());

        verify(petRepository).save(any(Pet.class));
    }

    @Test
    void shouldRejectABodyNamingADifferentPet() throws Exception {
        given(petRepository.findById(2)).willReturn(Optional.of(aPet(2)));

        mvc.perform(put("/owners/1/pets/2")
                .contentType(MediaType.APPLICATION_JSON)
                .content(BODY_FOR_PET_3))
            .andExpect(status().isBadRequest());

        verify(petRepository, never()).save(any(Pet.class));
    }

    @Test
    void shouldAnswerNotFoundForAPetThatDoesNotExist() throws Exception {
        given(petRepository.findById(99)).willReturn(Optional.empty());

        mvc.perform(put("/owners/1/pets/99")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"id\":99,\"name\":\"Basil\",\"birthDate\":\"2020-01-01\",\"typeId\":6}"))
            .andExpect(status().isNotFound());

        verify(petRepository, never()).save(any(Pet.class));
    }
}
